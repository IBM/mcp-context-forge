# Pagination controls hidden when UI hide sections/header items are enabled

## Bug Summary

Pagination navigation buttons disappear for visible sections when `MCPGATEWAY_UI_HIDE_SECTIONS` or `MCPGATEWAY_UI_HIDE_HEADER_ITEMS` are configured. The root cause is a Jinja2 variable scoping issue in `admin.html` where a shared `pagination` variable cascades between section blocks.

## Root Cause

### Jinja2 `pagination` variable cascade

In `admin.html`, five sections compute pagination inline and share a single `pagination` variable:

| Order | Section | Line |
|-------|---------|------|
| 1 | servers/catalog | 2496 |
| 2 | tools | 3444 |
| 3 | gateways | 4985 |
| 4 | tokens | 6665 |
| 5 | a2a-agents | 6811 |

Each section checks whether `pagination` already exists before computing its own values:

```jinja2
{% set total_items = (pagination.total_items if pagination is defined else (total_items if total_items is defined else (tools|length if tools is defined else 0))) %}
{% set total_pages = (pagination.total_pages if pagination is defined else ((total_items + per_page - 1) // per_page)) %}
```

Then reassigns the shared variable:

```jinja2
{% set pagination = { 'page': page, 'per_page': per_page, 'total_items': total_items, 'total_pages': total_pages, ... } %}
```

**Jinja2 scoping rule:** `{% set %}` inside `{% if %}` blocks propagates to the enclosing scope (unlike `{% for %}` loops). All section panels are guarded by `{% if 'section' not in hidden_sections %}`, but that does NOT create a new variable scope. After section #1 renders and sets `pagination`, section #2 reads section #1's `total_items` and `total_pages` instead of computing from its own data.

### How hiding sections triggers the visible bug

Hiding sections changes which section's stale data poisons subsequent ones. The most visible failure:

If a visible section before yours had **0 items**, it sets `pagination.total_pages = 0`. Your section inherits `totalPages: 0`, and in `pagination_controls.html` line 161:

```html
<template x-if="totalPages > 0">
  <!-- All navigation buttons are inside here -->
</template>
```

The navigation buttons disappear entirely even if your section has hundreds of items.

### Why HTMX doesn't always fix it

Partial templates use OOB swaps to update pagination correctly after load:

```html
<div id="tools-pagination-controls" hx-swap-oob="true">
  {% include 'pagination_controls.html' %}
</div>
```

But the initial HTMX load uses a timing-dependent pattern — Alpine.js `x-init` sets the `hx-get` URL dynamically:

```html
<div id="tools-table"
     x-init="$el.setAttribute('hx-get', buildTableUrl(...))"
     hx-trigger="load" ...>
```

If HTMX processes the `load` trigger before Alpine has set the `hx-get` attribute, the request silently fails and the stale cascade-contaminated pagination stays in place permanently.

### `mcpgateway_ui_hide_header_items` interaction

Hiding `team_selector` affects the `should_load_user_teams` logic in `admin.py:3111-3113`:

```python
should_load_user_teams = getattr(settings, "email_auth_enabled", False) and (
    team_id is not None or "team_selector" not in hidden_header_items or bool(sections_requiring_user_teams - hidden_sections)
)
```

When `team_selector` is hidden AND all team-dependent sections are hidden, `user_teams` stays `[]`. This can cascade into team-filtered data loading returning empty results for sections that are still visible, further contributing to `total_items = 0` → `total_pages = 0`.

## Reproduction

1. Set `MCPGATEWAY_UI_HIDE_SECTIONS=overview,logs` (or any combination that leaves multiple data sections visible)
2. Ensure the first visible section with pagination (servers/catalog) has 0 items
3. Navigate to the second visible section (tools) which has items
4. Observe: pagination navigation buttons (prev/next/page numbers) are missing

Alternatively:

1. Set `MCPGATEWAY_UI_HIDE_HEADER_ITEMS=team_selector` with `EMAIL_AUTH_ENABLED=true`
2. Hide enough sections that `should_load_user_teams` evaluates to `False`
3. Visible sections that depend on team-filtered data return empty results
4. Pagination cascade propagates `total_pages = 0` to subsequent sections

## Affected Files

- `mcpgateway/templates/admin.html` — Jinja2 `pagination` variable cascade (lines 2496, 3444, 4985, 6665, 6811)
- `mcpgateway/templates/pagination_controls.html` — `x-if="totalPages > 0"` hides navigation (line 161)
- `mcpgateway/admin.py` — `should_load_user_teams` logic (line 3111), empty data lists for hidden sections (lines 3325-3370)

## Suggested Fix

Each section should compute pagination from its own data independently rather than reading from a shared `pagination` variable. Options:

1. **Use distinct variable names per section** (e.g., `servers_pagination`, `tools_pagination`) so there is no cross-contamination between blocks.
2. **Always fall through to the section's own entity list** instead of checking `if pagination is defined` — remove the `pagination.total_items if pagination is defined` guard from each section's computation block.
3. **Reset pagination at the start of each section block** by adding `{% set pagination = none %}` at the top of each `{% if 'section' not in hidden_sections %}` block before computing new values.

Option 2 is the simplest and most correct — each section should unconditionally compute from its own data:

```jinja2
{# Instead of: #}
{% set total_items = (pagination.total_items if pagination is defined else (total_items if total_items is defined else (tools|length if tools is defined else 0))) %}

{# Use: #}
{% set total_items = tools|length if tools is defined else 0 %}
{% set total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 0 %}
```
