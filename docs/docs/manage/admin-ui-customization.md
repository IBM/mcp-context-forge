# Admin UI Customization

MCP Gateway's Admin UI supports flexible section visibility for embedding in third-party portals, restricting views for specific audiences, and reducing dashboard clutter. This guide covers environment-level configuration, per-request hiding, and embedded mode.

!!! info "UI Visibility vs. RBAC"
    Section visibility is a **UI convenience**, not a security boundary. Hidden sections are still accessible via API. Use [RBAC](rbac.md) to control data access.

## Quick Start

Hide specific sections and header items via environment variables:

```bash
# Hide the prompts and resources sections
MCPGATEWAY_UI_HIDE_SECTIONS=prompts,resources

# Hide the logout button and team selector
MCPGATEWAY_UI_HIDE_HEADER_ITEMS=logout,team_selector
```

Or hide sections per-request via query parameter:

```
https://gateway.example.com/admin/?ui_hide=prompts,resources,teams
```

## Environment Variables

### `MCPGATEWAY_UI_HIDE_SECTIONS`

Comma-separated or JSON list of sections to hide globally. Invalid values are logged and ignored.

**Valid sections:**

| Section | What It Hides |
|---------|---------------|
| `servers` | Catalog / virtual servers tab |
| `gateways` | Gateway connections tab |
| `tools` | Tools registry tab |
| `prompts` | Prompts registry tab |
| `resources` | Resources registry tab |
| `teams` | Team management tab |
| `users` | User management tab |
| `agents` | A2A agents tab |
| `tokens` | API tokens tab |
| `settings` | LLM / gateway settings tab |

**Aliases**: The following alternative names are also accepted:

| Alias | Resolves To |
|-------|-------------|
| `catalog` | `servers` |
| `virtual_servers` | `servers` |
| `a2a-agents` | `agents` |
| `a2a` | `agents` |
| `grpc-services` | `agents` |
| `api_tokens` | `tokens` |
| `llm-settings` | `settings` |

**Examples:**

```bash
# CSV format
MCPGATEWAY_UI_HIDE_SECTIONS=prompts,resources,teams

# JSON format
MCPGATEWAY_UI_HIDE_SECTIONS=["prompts","resources","teams"]

# Using aliases
MCPGATEWAY_UI_HIDE_SECTIONS=catalog,a2a-agents
```

### `MCPGATEWAY_UI_HIDE_HEADER_ITEMS`

Comma-separated or JSON list of header items to hide.

**Valid items:**

| Item | What It Hides |
|------|---------------|
| `logout` | Logout button |
| `team_selector` | Team dropdown selector |
| `user_identity` | Username display |
| `theme_toggle` | Light/dark theme switch |

```bash
MCPGATEWAY_UI_HIDE_HEADER_ITEMS=logout,team_selector
```

### `MCPGATEWAY_UI_EMBEDDED`

Boolean flag that enables embedded mode. When `true`, automatically hides `logout` and `team_selector` header items (since the parent application typically handles authentication).

```bash
MCPGATEWAY_UI_EMBEDDED=true
```

This is equivalent to setting `MCPGATEWAY_UI_HIDE_HEADER_ITEMS=logout,team_selector` but communicates intent more clearly. If both are set, the values are merged.

## Per-Request Hiding with `?ui_hide=`

For embedded contexts where different pages need different views, use the `?ui_hide=` query parameter:

```
/admin/?ui_hide=prompts,resources,teams
```

### Cookie Persistence

The query parameter value is stored in an `httponly` cookie (`mcpgateway_ui_hide_sections`) with a 30-day lifetime. Subsequent requests to `/admin/` without the query parameter will use the cookie value. This means iframe reloads maintain the same view.

### Clearing Preferences

Visit with an empty value to clear the cookie and restore the full view:

```
/admin/?ui_hide=
```

### Merge Behavior

Per-request values are **merged** with environment-level configuration. If the environment hides `users` and a request adds `?ui_hide=tools`, both `users` and `tools` are hidden.

## Embedding in an Iframe

A typical embedding scenario:

```html
<iframe
  src="https://gateway.example.com/admin/?ui_hide=users,teams,tokens,settings"
  style="width: 100%; height: 100vh; border: none;"
></iframe>
```

With environment configuration:

```bash
MCPGATEWAY_UI_EMBEDDED=true
MCPGATEWAY_UI_HIDE_SECTIONS=users,teams,tokens,settings
```

This produces a streamlined view showing only servers, gateways, tools, prompts, and resources — without the logout button or team selector.

## Docker Compose Example

```yaml
services:
  mcpgateway:
    image: mcpgateway:latest
    environment:
      - MCPGATEWAY_UI_ENABLED=true
      - MCPGATEWAY_UI_EMBEDDED=true
      - MCPGATEWAY_UI_HIDE_SECTIONS=users,teams,tokens,settings
      - MCPGATEWAY_UI_HIDE_HEADER_ITEMS=logout,team_selector
```

## Helm Chart

```yaml
# values.yaml
mcpgateway:
  env:
    MCPGATEWAY_UI_EMBEDDED: "true"
    MCPGATEWAY_UI_HIDE_SECTIONS: "users,teams,tokens,settings"
    MCPGATEWAY_UI_HIDE_HEADER_ITEMS: "logout,team_selector"
```

## Performance

Hidden sections are optimized at the server level. When a section is hidden, the Admin UI endpoint **skips the corresponding database queries entirely**. For example, hiding `tools` prevents the tools table query, hiding `teams` skips team enumeration. This reduces response time and database load for partial-view deployments.

## Architecture

For the design rationale behind this feature, see [ADR-0040: Flexible Admin UI Section Visibility](../architecture/adr/040-flexible-admin-ui-sections.md).
