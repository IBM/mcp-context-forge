# ADR-0040: Flexible Admin UI Section Visibility

- *Status:* Accepted
- *Date:* 2026-02-16
- *Deciders:* Mihai Criveti

## Context

MCP Gateway's Admin UI is a full-featured dashboard with 10+ sections (servers, gateways, tools, prompts, resources, teams, users, agents, tokens, settings). When the UI is embedded inside a third-party portal via iframe, or when an operator wants to expose only a subset of functionality to certain audiences, the full dashboard is too broad. There was no mechanism to hide irrelevant sections, header controls (logout, team selector), or prevent data loading for hidden sections.

Key requirements:

- **Embedding**: Third-party portals need to embed the Admin UI with only relevant sections visible and without redundant header controls like logout.
- **Operator control**: Platform operators need to restrict which sections are visible at the environment level, independent of RBAC (which controls data access, not UI visibility).
- **Per-request customization**: Embedded iframes need to vary visible sections per context (e.g., one page shows only tools, another shows only gateways).
- **Performance**: Hidden sections should not load data from the database.

## Decision

Implement a three-layer UI visibility system:

### Layer 1: Environment-Level Configuration

Three new environment variables control defaults:

| Variable | Type | Purpose |
|----------|------|---------|
| `MCPGATEWAY_UI_EMBEDDED` | `bool` | Embedded mode — auto-hides `logout` and `team_selector` header items |
| `MCPGATEWAY_UI_HIDE_SECTIONS` | CSV/JSON list | Sections to hide globally |
| `MCPGATEWAY_UI_HIDE_HEADER_ITEMS` | CSV/JSON list | Header items to hide globally |

All values are validated at startup against frozen allowlists (`UI_HIDABLE_SECTIONS`, `UI_HIDABLE_HEADER_ITEMS`) defined in `config.py`. Unknown values are logged and dropped.

### Layer 2: Per-Request Query Parameter

The `?ui_hide=section1,section2` query parameter allows per-request section hiding. The value is persisted in an `httponly` cookie (`mcpgateway_ui_hide_sections`, 30-day max age) so subsequent requests remember the preference. Visiting `?ui_hide=` (empty) clears the cookie.

### Layer 3: Client-Side Tab Navigation

JavaScript globals (`UI_HIDDEN_TABS`, `UI_HIDDEN_SECTIONS`) are set from the server-rendered template. Client-side functions (`isTabHidden`, `resolveTabForNavigation`, `getDefaultTabName`) prevent navigation to hidden tabs and filter search results.

### Section Aliases

A canonical alias map resolves alternative section names:

```python
UI_HIDE_SECTION_ALIASES = {
    "catalog": "servers",
    "virtual_servers": "servers",
    "a2a-agents": "agents",
    "a2a": "agents",
    "grpc-services": "agents",
    "api_tokens": "tokens",
    "llm-settings": "settings",
}
```

### Server-Side Data Optimization

When a section is hidden, the `admin_ui()` endpoint skips the corresponding database queries entirely. This reduces latency and load for partial-view scenarios.

## Consequences

### Positive

- Embedding the Admin UI in third-party portals is straightforward with `?ui_hide=` and `MCPGATEWAY_UI_EMBEDDED=true`
- Operators can restrict visible sections without modifying code or templates
- Hidden sections incur zero database cost (server-side skip)
- Cookie persistence means iframe reloads maintain the same view
- Alias system provides forward-compatible naming as the UI evolves

### Negative

- UI visibility is not a security boundary — hidden sections are still accessible via API. RBAC remains the access control mechanism.
- Cookie-based persistence means browser-clearing resets preferences (acceptable for embedded use)

### Risks / Mitigations

- **Stale cookies after config change**: If an operator changes `UI_HIDE_SECTIONS`, stale cookies may show outdated preferences. Mitigated by the 30-day cookie expiry and the ability to clear with `?ui_hide=`.
- **CSS selector injection in tab names**: Mitigated by the `normalizeTabName()` character whitelist (`/[^a-z0-9-]/g`).

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| RBAC-only visibility | RBAC controls data access, not UI layout. Operators want UI customization independent of permissions. |
| Template-level config files | Requires template redeployment. Env vars and query params are more flexible for container/iframe use. |
| Client-side only hiding (CSS/JS) | Would still load all data server-side, wasting resources. Server-side awareness is necessary for optimization. |
| URL path-based views (`/admin/tools-only/`) | Creates multiple endpoints to maintain. Query parameter approach is composable and doesn't multiply routes. |

## Related

- Configuration: [Admin UI Customization](../../manage/admin-ui-customization.md)
- Reference: [Configuration Reference](../../manage/configuration.md#ui-features)
